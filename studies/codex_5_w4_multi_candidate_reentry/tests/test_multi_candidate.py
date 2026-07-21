from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

MODULE_PATH = Path(__file__).resolve().parents[1] / "run_study.py"
SPEC = importlib.util.spec_from_file_location("multi_candidate", MODULE_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)

BASE = 1_800_000_000_000_000_000
NS = 1_000_000_000


def bars(count: int = 500) -> pd.DataFrame:
    index = pd.to_datetime(BASE + np.arange(count, dtype=np.int64) * NS, utc=True)
    return pd.DataFrame({"open": 100.0, "high": 110.0, "low": 99.0,
                         "close": 100.0, "volume": 1.0}, index=index)


def candidate_frame(times=(0, 15), end_s=90, flip_s=100) -> pd.DataFrame:
    rows = []
    for seq, sec in enumerate(times, 1):
        rows.append({"year": 2025, "opportunity_id": "opp", "candidate_id": f"opp_c{seq:03d}",
            "candidate_seq": seq, "regime_start_ns": BASE, "confirm_flip_ns": BASE + flip_s * NS,
            "prevailing_direction": -1, "entry_direction": 1,
            "candidate_time": BASE + sec * NS, "candidate_fill_time": BASE + sec * NS,
            "candidate_fill_price": 100.0, "w4_score": 0.8, "threshold": 0.7,
            "score_margin": 0.1, "atr_at_checkpoint": 10.0, "regime_age_s": sec,
            "running_mfe_atr": 1.0, "running_mae_atr": 0.0,
            "new_progress_windows": 2, "retained_mfe_ratio": 1.0,
            "direction": "long_fade", "session": "ETH",
            "opportunity_end_ts": BASE + end_s * NS,
            "opportunity_end_reason": "established_filter_ended",
            "candidate_count_in_opportunity": len(times)})
    return pd.DataFrame(rows)


def synthetic_stream() -> pd.DataFrame:
    seconds = [5, 10, 15, 20, 25, 30, 35]
    scores = [0.5, 0.8, 0.6, 0.9, 0.9, 0.6, 0.9]
    pnl = [0.1, 0.1, 0.1, 0.1, 0.0, 0.1, 0.1]
    return pd.DataFrame({"observation_time": [BASE + s * NS for s in seconds],
        "regime_start_ns": BASE, "regime_end_ns": BASE + 80 * NS, "direction": -1,
        "entry_ts_event": BASE, "entry_open": 100.0, "atr_at_entry": 10.0,
        "atr_at_checkpoint": 10.0, "regime_age": seconds, "current_pnl": pnl,
        "current_mfe": 0.1, "current_mae": 0.0, "running_mfe": 0.1,
        "running_mae": 0.0, "w4_score": scores, "direction_threshold": 0.7,
        "score_valid": True})


def test_collector_emits_strict_recross_not_plateau_and_stops_at_filter_end(monkeypatch):
    monkeypatch.setattr(mod, "load_checkpoint_stream", lambda year, policy: synthetic_stream())
    policy = {"filter": {"regime_age_s_min": 0.0, "running_mfe_atr_min": 0.0,
                         "new_progress_windows_min": 0, "retained_mfe_ratio_min": 0.5}}
    candidates, audit = mod.collect_candidates(2025, bars(100), policy, 1800)
    assert candidates.candidate_seq.tolist() == [1, 2]
    assert candidates.candidate_time.tolist() == [BASE + 10 * NS, BASE + 20 * NS]
    assert candidates.opportunity_end_ts.nunique() == 1
    assert int(candidates.opportunity_end_ts.iloc[0]) == BASE + 25 * NS
    assert "after_opportunity_end" in set(audit.generation_reason)


def test_later_recross_at_1800_is_inclusive_but_after_horizon_is_excluded(monkeypatch):
    seconds = [1785, 1790, 1795, 1800, 1805, 1810]
    stream = pd.DataFrame({"observation_time": [BASE + s * NS for s in seconds],
        "regime_start_ns": BASE, "regime_end_ns": BASE + 1900 * NS, "direction": -1,
        "entry_ts_event": BASE, "entry_open": 100.0, "atr_at_entry": 10.0,
        "atr_at_checkpoint": 10.0, "regime_age": seconds, "current_pnl": 0.1,
        "current_mfe": 0.1, "current_mae": 0.0, "running_mfe": 0.1,
        "running_mae": 0.0, "w4_score": [0.5, 0.8, 0.5, 0.8, 0.5, 0.8],
        "direction_threshold": 0.7, "score_valid": True})
    monkeypatch.setattr(mod, "load_checkpoint_stream", lambda year, policy: stream)
    policy = {"filter": {"regime_age_s_min": 0.0, "running_mfe_atr_min": 0.0,
                         "new_progress_windows_min": 0, "retained_mfe_ratio_min": 0.5}}
    candidates, _ = mod.collect_candidates(2025, bars(1901), policy, 1800)
    assert candidates.regime_age_s.tolist() == [1790.0, 1800.0]
    assert candidates.candidate_seq.tolist() == [1, 2]


def test_r10_rejects_first_and_accepts_later_recross():
    raw = bars()
    raw.iloc[9, raw.columns.get_loc("close")] = 99.0
    raw.iloc[24, raw.columns.get_loc("close")] = 101.0
    raw.iloc[26, raw.columns.get_loc("open")] = 102.0
    selected, evaluated = mod.select_candidates(candidate_frame(), raw, "R10", 10)
    assert selected.candidate_accepted.iloc[0]
    assert int(selected.candidate_seq.iloc[0]) == 2
    assert int(selected.actual_entry_fill_ts.iloc[0]) == BASE + 26 * NS
    assert evaluated.evaluation_reason.tolist() == ["adverse_virtual_response", "accepted"]


def test_crossing_during_confirmation_wait_is_not_queued():
    raw = bars()
    raw.iloc[9, raw.columns.get_loc("close")] = 99.0
    raw.iloc[29, raw.columns.get_loc("close")] = 101.0
    candidates = candidate_frame(times=(0, 5, 20))
    selected, evaluated = mod.select_candidates(candidates, raw, "R10", 10)
    assert evaluated.evaluation_reason.iloc[1] == "not_queued_during_confirmation_wait"
    assert int(selected.candidate_seq.iloc[0]) == 3


def test_zero_response_approves_and_fill_is_strictly_after_gate():
    selected, evaluated = mod.select_candidates(candidate_frame(times=(0,)), bars(), "R10", 10)
    assert selected.candidate_accepted.iloc[0]
    assert int(selected.actual_entry_fill_ts.iloc[0]) == BASE + 11 * NS
    assert float(selected.virtual_directional_pnl_points.iloc[0]) == 0.0
    assert evaluated.accepted.iloc[0]


def test_r0_uses_immediate_candidate_fill():
    selected, _ = mod.select_candidates(candidate_frame(times=(0,)), bars(), "R0", 0)
    assert selected.candidate_accepted.iloc[0]
    assert int(selected.actual_entry_fill_ts.iloc[0]) == BASE
    assert float(selected.actual_entry_fill_price.iloc[0]) == 100.0


def test_regime_end_before_confirmation_terminates_opportunity():
    selected, evaluated = mod.select_candidates(candidate_frame(times=(0, 15), flip_s=10), bars(), "R10", 10)
    assert not selected.candidate_accepted.iloc[0]
    assert evaluated.evaluation_reason.iloc[0] == "regime_ended_before_confirmation"
    assert len(evaluated) == 1


def test_filter_end_before_confirmation_rejects_as_opportunity_ended():
    selected, evaluated = mod.select_candidates(candidate_frame(times=(0,), end_s=10), bars(), "R10", 10)
    assert not selected.candidate_accepted.iloc[0]
    assert evaluated.evaluation_reason.iloc[0] == "opportunity_ended"


def test_delayed_fill_stop_is_active_on_entry_bar():
    raw = bars()
    c = pd.Series({"actual_entry_fill_ts": BASE + 11 * NS, "actual_entry_fill_price": 102.0,
        "entry_direction": 1, "atr_at_checkpoint": 10.0, "confirm_flip_ns": BASE + 400 * NS})
    raw.iloc[11, raw.columns.get_loc("open")] = 102.0
    raw.iloc[11, raw.columns.get_loc("low")] = 88.0
    result = mod.simulate_trade(c, raw, BASE + 450 * NS)
    assert result["stop_submission_ts"] == BASE + 11 * NS
    assert result["stop_active_entry_bar"]
    assert result["exit_fill_ts"] == BASE + 11 * NS
    assert result["exit_fill_px"] == 89.5


def test_timeout_restarts_at_actual_entry_and_fills_strictly_after():
    raw = bars()
    c = pd.Series({"actual_entry_fill_ts": BASE + 11 * NS, "actual_entry_fill_price": 100.0,
        "entry_direction": 1, "atr_at_checkpoint": 10.0, "confirm_flip_ns": BASE + 400 * NS})
    raw.iloc[312, raw.columns.get_loc("open")] = 103.0
    result = mod.simulate_trade(c, raw, BASE + 450 * NS)
    assert result["timeout_ts"] == BASE + 311 * NS
    assert result["exit_fill_ts"] == BASE + 312 * NS
    assert result["exit_fill_px"] == 103.0
    assert result["exit_reason"] == "confirmation_timeout_exit"
