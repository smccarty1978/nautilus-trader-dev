from research_workflow.first_p90_warning import (
    FirstP90Warning, first_inclusive_p90_warning, followup_terminal, warning_subtype,
    control_cell, select_control, project_first_p90_march,
)
import pandas as pd


def test_first_warning_is_inclusive_and_resets_by_regime():
    rows = [{"regime_id": "a", "direction": "LONG", "ts": 1, "eligible": True, "score": .2},
            {"regime_id": "a", "direction": "LONG", "ts": 2, "eligible": True, "score": .3},
            {"regime_id": "b", "direction": "LONG", "ts": 3, "eligible": True, "score": .3}]
    assert [(x.regime_id, x.warning_ts) for x in first_inclusive_p90_warning(rows, {"LONG": .3})] == [("a", 2), ("b", 3)]


def test_followup_continues_after_eligibility_and_preserves_market_outcome():
    w = FirstP90Warning("a", "LONG", 0, .3, .3)
    result = followup_terminal(w, [{"ts": 5_000_000_000, "scheduled_score": True, "eligible": False, "score": .2},
                                   {"ts": 10_000_000_000, "accepted_opposing_flip": True}], rth_close_ts=1_000_000_000_000)
    assert result["scores"][0]["score"] == .2 and result["time_to_flip_seconds"] == 10
    assert warning_subtype(result, .3) == "FAST"


def test_score_censor_is_distinct_from_market_censor_and_subtype_precedence():
    w = FirstP90Warning("a", "LONG", 0, .3, .3)
    result = followup_terminal(w, [{"ts": 5_000_000_000, "scheduled_score": True, "score": None}], rth_close_ts=600_000_000_000)
    assert result["market_outcome_status"] == "OBSERVED"
    assert result["score_path_status"] == "CENSORED"
    assert warning_subtype(result, .3) == "SESSION_CENSORED"


def test_control_is_latest_below_threshold_strictly_before_fire_and_bucket_edges():
    rows = [{"regime_id": "a", "ts": 300_000_000_000, "age_seconds": 300, "valid": True, "score": .2},
            {"regime_id": "a", "ts": 305_000_000_000, "age_seconds": 305, "valid": True, "score": .25},
            {"regime_id": "a", "ts": 310_000_000_000, "age_seconds": 310, "valid": True, "score": .3}]
    w = FirstP90Warning("a", "LONG", 310_000_000_000, .3, .3)
    assert control_cell(rows[0], rth_open_ts=0)[0] == "[300,600)"
    assert select_control(rows, w, rth_open_ts=0)["ts"] == 305_000_000_000


def test_march_projection_keeps_180_boundary_and_censors_pre_horizon_terminal():
    ns = 1_000_000_000
    d = pd.DataFrame([
        {"regime_start_ns": 1, "direction": "LONG", "anchor_ts": 0, "scheduled_ts": 0,
         "terminal_ts": 180 * ns, "terminal_reason": "ACCEPTED_OPPOSING_FLIP", "market_path_status": "OBSERVED"},
        {"regime_start_ns": 2, "direction": "SHORT", "anchor_ts": 0, "scheduled_ts": 0,
         "terminal_ts": 179 * ns, "terminal_reason": "RTH_CLOSE", "market_path_status": "OBSERVED"},
    ])
    out = project_first_p90_march(d).sort_values("regime_start_ns")
    assert out.iloc[0].target_flip_within_horizon == 1
    assert pd.isna(out.iloc[1].target_flip_within_horizon) and bool(out.iloc[1].censored)
